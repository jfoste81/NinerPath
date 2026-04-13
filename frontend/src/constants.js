export const API_BASE = import.meta.env.VITE_API_BASE ?? 'https://ninerpath.onrender.com/';

export const CONCENTRATIONS_BY_DEGREE = {
  bs_computer_science: [
    { value: 'systems_and_networks', label: 'Systems and Networks' },
    { value: 'ai_robotics_and_gaming', label: 'AI, Robotics and Gaming' },
    { value: 'bioinformatics', label: 'Bioinformatics' },
    { value: 'cybersecurity', label: 'Cybersecurity' },
    { value: 'data_science', label: 'Data Science' },
    { value: 'web_mobile_and_software_engineering', label: 'Web/Mobile Development & Software Engineering' },
  ],
  ba_computer_science: [
    { value: 'information_technology', label: 'Information Technology' },
    { value: 'human_computer_interaction', label: 'Human-Computer Interaction' },
    { value: 'bioinformatics', label: 'Bioinformatics' },
  ],
};
